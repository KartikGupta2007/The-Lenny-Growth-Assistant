import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Fail loudly if the port is taken. Vite otherwise moves to 5174 silently,
    // which leaves the documented URL pointing at nothing.
    strictPort: true,
    // Bind both stacks. The default binds IPv6 only, so http://127.0.0.1:5173
    // -- and localhost on any machine that resolves IPv4 first -- is refused.
    host: true,
  },
})
