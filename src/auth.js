const TOKEN_KEY = 'site_auth_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

/**
 * جایگزین fetch معمولی — خودکار توکن ورود رو به هدر اضافه می‌کنه و اگه
 * سرور بگه توکن نامعتبره (۴۰۱)، کاربر رو برمی‌گردونه به صفحه‌ی ورود.
 */
export async function authFetch(url, options = {}) {
  const token = getToken()
  const headers = {
    ...(options.headers || {}),
    Authorization: `Bearer ${token || ''}`,
  }
  const res = await fetch(url, { ...options, headers })
  if (res.status === 401) {
    clearToken()
    window.location.reload()
  }
  return res
}
