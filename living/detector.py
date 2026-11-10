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
    """EfficientDet-Lite0 TFLite (MediaPipe ObjectDetector). 사람만 돌려준다."""

    def __init__(self, model_path, conf=0.4):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        self.mp = mp
        options = vision.ObjectDetectorOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            score_threshold=conf,
            category_allowlist=["person"],
            max_results=10,
        )
        self.detector = vision.ObjectDetector.create_from_options(options)

    def detect(self, frame):
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB,
                              data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        result = []
        for d in self.detector.detect(image).detections:
            b = d.bounding_box
            result.append((b.origin_x, b.origin_y, b.origin_x + b.width, b.origin_y + b.height,
                           d.categories[0].score))
        return result

    def close(self):
        self.detector.close()


def make_detector(cfg):
    """config.json 의 detector 항목으로 검출기를 만든다."""
    if cfg["type"] == "yolo":
        return YoloDetector(cfg["yolo_model"], imgsz=cfg.get("imgsz", 320), conf=cfg.get("conf", 0.4))
    if cfg["type"] == "effdet":
        return EfficientDetDetector(cfg["effdet_model"], conf=cfg.get("conf", 0.4))
    raise ValueError(f"모르는 검출기: {cfg['type']}")
