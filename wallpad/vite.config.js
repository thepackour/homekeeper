import { existsSync, readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 브로커 주소는 팀 저장소 common/config.json 한 곳에서만 읽는다(이 폴더 옆의 common/).
// 빌드할 때 읽어서 화면 코드의 __COMMON_CONFIG__ 자리에 넣는다.
// 저장소 밖에서 실행하면 파일이 없으니 null → 화면에서 주소를 직접 입력한다.
const commonConfig = new URL('../common/config.json', import.meta.url)
const common = existsSync(commonConfig) ? JSON.parse(readFileSync(commonConfig, 'utf8')) : null

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __COMMON_CONFIG__: JSON.stringify(common),
  },
})
