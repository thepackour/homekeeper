"""사람 검출. 모델마다 클래스는 다르지만 detect() 모양은 같다.

detect(frame) -> [(x1, y1, x2, y2, score), ...]  # 원본 프레임 픽셀 좌표, 사람만
"""
import cv2
import numpy as np


class YoloDetector:
    """YOLOv8n / YOLO11n ONNX (onnxruntime). 사람(class 0)만 돌려준다."""

    def __init__(self, model_path, imgsz=320, conf=0.4, iou=0.5):
        import onnxruntime as ort
        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.imgsz, self.conf, self.iou = imgsz, conf, iou

    def detect(self, frame):
        h, w = frame.shape[:2]
        # 비율 유지하며 imgsz 정사각형에 넣기(남는 곳은 회색)
        scale = self.imgsz / max(h, w)
        nh, nw = round(h * scale), round(w * scale)
        canvas = np.full((self.imgsz, self.imgsz, 3), 114, dtype=np.uint8)
        top, left = (self.imgsz - nh) // 2, (self.imgsz - nw) // 2
        canvas[top:top + nh, left:left + nw] = cv2.resize(frame, (nw, nh))
        blob = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255

        out = self.session.run(None, {self.input_name: blob})[0][0]   # (84, N): cx,cy,w,h + 80 클래스
        scores = out[4]                                                # 0번 = person
        keep = scores > self.conf
        if not keep.any():
            return []
        cx, cy, bw, bh = out[0][keep], out[1][keep], out[2][keep], out[3][keep]
        scores = scores[keep]
        # 정사각형 좌표 → 원본 좌표
        x1 = (cx - bw / 2 - left) / scale
        y1 = (cy - bh / 2 - top) / scale
        boxes = [[float(a), float(b), float(c), float(d)] for a, b, c, d in zip(x1, y1, bw / scale, bh / scale)]
        idx = cv2.dnn.NMSBoxes(boxes, scores.tolist(), self.conf, self.iou)
        result = []
        for i in np.array(idx).flatten():
            x, y, bw_, bh_ = boxes[i]
            result.append((max(0, x), max(0, y), min(w, x + bw_), min(h, y + bh_), float(scores[i])))
        return result

    def close(self):
        pass


class EfficientDetDetector:
    """EfficientDet-Lite0 (NMS 포함 모델). 사람만 돌려준다.

    .onnx  → onnxruntime 으로 실행(파이 400용. models/effdet_to_onnx.py 로 변환)
    .tflite → LiteRT(ai-edge-litert 또는 tflite_runtime)로 실행
    mediapipe·LiteRT 는 파이 400 CPU에 없는 AES 명령을 써서 파이에서는 .onnx 를 쓴다.
    출력 4개: 상자(1,N,4: ymin,xmin,ymax,xmax 0~1), 클래스(1,N), 점수(1,N), 개수(1).
    """

    def __init__(self, model_path, conf=0.4, threads=4):
        self.conf = conf
        if str(model_path).endswith(".onnx"):
            import onnxruntime as ort
            self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
            inp = self.session.get_inputs()[0]
            self.input_name = inp.name
            self.size = (int(inp.shape[2]), int(inp.shape[1]))         # (너비, 높이)
            self.input_dtype = np.uint8 if "uint8" in inp.type else np.float32
            outs = sorted(self.session.get_outputs(), key=lambda o: o.name)
            self.out_names = [o.name for o in outs]
            self._run = self._run_onnx
            shapes = [len(o.shape) for o in outs]
        else:
            try:
                from ai_edge_litert.interpreter import Interpreter
            except ImportError:
                from tflite_runtime.interpreter import Interpreter
            self.it = Interpreter(model_path, num_threads=threads)
            self.it.allocate_tensors()
            inp = self.it.get_input_details()[0]
            self.input_index, self.input_dtype = inp["index"], inp["dtype"]
            self.size = (int(inp["shape"][2]), int(inp["shape"][1]))
            outs = sorted(self.it.get_output_details(), key=lambda d: d["name"])
            self.out_idx = [d["index"] for d in outs]
            self._run = self._run_tflite
            shapes = [len(d["shape"]) for d in outs]
        # 이름 순서(:0 개수, :1 점수, :2 클래스, :3 상자)에서 상자는 3차원, 점수·클래스는 2차원
        self.boxes_i = shapes.index(3)
        self.scores_i, self.classes_i = [i for i, n in enumerate(shapes) if n == 2]

    def _run_onnx(self, x):
        return self.session.run(self.out_names, {self.input_name: x})

    def _run_tflite(self, x):
        self.it.set_tensor(self.input_index, x)
        self.it.invoke()
        return [self.it.get_tensor(i) for i in self.out_idx]

    def detect(self, frame):
        h, w = frame.shape[:2]
        x = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), self.size)[None].astype(self.input_dtype)
        out = self._run(x)
        boxes, classes, scores = out[self.boxes_i][0], out[self.classes_i][0], out[self.scores_i][0]
        result = []
        for (y1, x1, y2, x2), c, sc in zip(boxes, classes, scores):
            if int(c) == 0 and sc >= self.conf:            # 0 = person
                result.append((max(0.0, float(x1) * w), max(0.0, float(y1) * h),
                               min(w, float(x2) * w), min(h, float(y2) * h), float(sc)))
        return result

    def close(self):
        pass


def make_detector(cfg):
    """config.json 의 detector 항목으로 검출기를 만든다."""
    if cfg["type"] == "yolo":
        return YoloDetector(cfg["yolo_model"], imgsz=cfg.get("imgsz", 320), conf=cfg.get("conf", 0.4))
    if cfg["type"] == "effdet":
        return EfficientDetDetector(cfg["effdet_model"], conf=cfg.get("conf", 0.4))
    raise ValueError(f"모르는 검출기: {cfg['type']}")
