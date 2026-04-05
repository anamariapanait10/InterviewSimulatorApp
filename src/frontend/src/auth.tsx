import { createContext, useContext, useEffect, useState } from 'react'
import type { PropsWithChildren } from 'react'
import { getCurrentUser, loginUser, logoutUser, registerUser } from './api'
import {
  AUTH_EVENT,
  clearStoredAuthToken,
  getStoredAuthToken,
  setStoredAuthToken,
} from './authStorage'
import type { User } from './types'

interface AuthContextValue {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: PropsWithChildren) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const token = getStoredAuthToken()
    if (!token) {
      setIsLoading(false)
      return
    }

    let cancelled = false

    const restoreSession = async () => {
      try {
        const currentUser = await getCurrentUser()
        if (!cancelled) {
          setUser(currentUser)
        }
      } catch {
        clearStoredAuthToken()
        if (!cancelled) {
          setUser(null)
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void restoreSession()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const handleAuthChange = () => {
      if (!getStoredAuthToken()) {
        setUser(null)
      }
    }

    window.addEventListener(AUTH_EVENT, handleAuthChange)
    return () => {
      window.removeEventListener(AUTH_EVENT, handleAuthChange)
    }
  }, [])

  const login = async (email: string, password: string) => {
    const payload = await loginUser(email, password)
    setStoredAuthToken(payload.token)
    setUser(payload.user)
  }

  const register = async (email: string, password: string) => {
    const payload = await registerUser(email, password)
    setStoredAuthToken(payload.token)
    setUser(payload.user)
  }

  const logout = async () => {
    try {
      await logoutUser()
    } catch {
      // Ignore logout failures and clear the local session anyway.
    } finally {
      clearStoredAuthToken()
      setUser(null)
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: Boolean(user),
        isLoading,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
