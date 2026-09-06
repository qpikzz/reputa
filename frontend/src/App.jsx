import { useMemo } from 'react'
import { createBrowserRouter, createRoutesFromElements, RouterProvider, Route } from 'react-router-dom'
import Landing from './components/Landing'
import Login from './components/Login'
import LoginWork from './components/LoginWork'
import Registration from './components/Registration'
import RegistrationWork from './components/RegistrationWork'
import ForgotPassword from './components/ForgotPassword'
import ResetPassword from './components/ResetPassword'
import UserNew from './components/UserNew'
import UserMy from './components/UserMy'
import UserSettings from './components/UserSettings'
import EmployeeSettings from './components/EmployeeSettings'
import EmployeeNewApplication from './components/EmployeeNewApplication'
import EmployeeApplication from './components/EmployeeApplication'
import RequireAuth from './components/RequireAuth'
import { AuthProvider } from './contexts/AuthContext'

// Маршруты описываются декларативно, но монтируются через data router
// (createBrowserRouter): useBlocker на странице настроек (предупреждение об
// уходе с несохранёнными изменениями) работает только под data router.
export default function App() {
  const router = useMemo(
    () =>
      createBrowserRouter(
        createRoutesFromElements(
          <>
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<Login />} />
            <Route path="/registration" element={<Registration />} />
            <Route path="/registrationWork" element={<RegistrationWork />} />
            <Route path="/loginWork" element={<LoginWork />} />
            <Route path="/forgot" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route element={<RequireAuth />}>
              <Route path="/user/settings" element={<UserSettings />} />
              <Route path="/user/my" element={<UserMy />} />
              <Route path="/user/new" element={<UserNew />} />
              <Route path="/employee/settings" element={<EmployeeSettings />} />
              <Route path="/employee/newApplication" element={<EmployeeNewApplication />} />
              <Route path="/employee/application" element={<EmployeeApplication />} />
            </Route>
          </>,
        ),
      ),
  )

  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  )
}