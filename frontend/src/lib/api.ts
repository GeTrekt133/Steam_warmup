import axios from 'axios'

declare global {
  interface Window {
    electronAPI?: {
      getBackendUrl: () => string
      platform: string
      openFile: (options: object) => Promise<{ canceled: boolean; filePaths: string[] }>
      openDirectory: (options?: object) => Promise<{ canceled: boolean; filePaths: string[] }>
      readTextFile: (filePath: string) => Promise<string>
      readDirectory: (dirPath: string) => Promise<{ name: string; path: string; isFile: boolean }[]>
      readFile: (filePath: string) => Promise<string>
      renameFile: (oldPath: string, newPath: string) => Promise<boolean>
    }
  }
}

const api = axios.create({
  baseURL: window.electronAPI?.getBackendUrl() ?? 'http://127.0.0.1:8420',
  timeout: 10000,
})

// Добавляем JWT токен к каждому запросу
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// При 401 — убираем токен и редиректим на логин
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token')
      localStorage.removeItem('current_user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api
