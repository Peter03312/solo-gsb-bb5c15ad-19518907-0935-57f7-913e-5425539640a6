import { useEffect, useState } from 'react'

/** Persisted state in the browser's localStorage (local storage requirement). */
export function useLocalStorage(key, initialValue) {
  const [value, setValue] = useState(() => {
    try {
      const raw = window.localStorage.getItem(key)
      return raw !== null ? JSON.parse(raw) : initialValue
    } catch {
      return initialValue
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value))
    } catch {
      /* storage may be unavailable; the app still works for this session */
    }
  }, [key, value])

  return [value, setValue]
}
