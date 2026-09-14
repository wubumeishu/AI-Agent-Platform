import axios from 'axios'

// 响应格式
export interface ApiResponse<T = unknown> {
  code: number
  message?: string
  data: T
}

// 分页响应
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// 创建 axios 实例
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001/api/v1',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`)
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response: any) => {
    const body = response.data

    // 部分路由（CRM 等）返回 {code, message, data} 信封；
    // FastAPI 原生路由（workflows / agents / execution-logs 等）直接返回裸模型。
    // 两者都要兼容：识别出信封才走信封解包，否则原样透传。
    const isEnvelope =
      body !== null &&
      typeof body === 'object' &&
      !Array.isArray(body) &&
      'code' in body &&
      ('message' in body || 'data' in body)

    if (isEnvelope) {
      const { code, message, data } = body
      if (code === 0) {
        response.data = data
        return response
      }
      // 业务错误
      const error: any = new Error(message || '请求失败')
      error.code = code
      error.isBusinessError = true
      return Promise.reject(error)
    }

    // 裸模型 / 204 等：保持原样
    return response
  },
  (error: any) => {
    const status = error.response?.status
    let message = '网络错误'
    
    switch (status) {
      case 401:
        message = '未授权，请重新登录'
        break
      case 403:
        message = '权限不足'
        break
      case 404:
        message = '请求资源不存在'
        break
      case 500:
        message = '服务器错误'
        break
      default:
        message = error.message || '请求失败'
    }
    
    error.message = message
    return Promise.reject(error)
  }
)

// 通用请求方法
export const api = {
  get<T = unknown>(url: string, config?: any): Promise<T> {
    return apiClient.get(url, config).then((response: any) => response.data) as Promise<T>
  },

  post<T = unknown>(url: string, data?: unknown, config?: any): Promise<T> {
    return apiClient.post(url, data, config).then((response: any) => response.data) as Promise<T>
  },

  put<T = unknown>(url: string, data?: unknown, config?: any): Promise<T> {
    return apiClient.put(url, data, config).then((response: any) => response.data) as Promise<T>
  },

  delete<T = unknown>(url: string, config?: any): Promise<T> {
    return apiClient.delete(url, config).then((response: any) => response.data) as Promise<T>
  },
}

export default apiClient
