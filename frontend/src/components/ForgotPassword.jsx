import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { postJSON } from '../api'
import { SHOW_AUTH_ILLUSTRATION } from '../constants/auth'
import './Login.css'

export default function ForgotPassword() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [identifier, setIdentifier] = useState('')
  const [touched, setTouched] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(event) {
    event.preventDefault()
    setTouched(true)
    if (!identifier.trim()) return

    setError('')
    const result = await postJSON('/api/auth/password-reset/request', { identifier: identifier.trim() })
    if (!result.ok) {
      setError(result.error || t('forgotPassword.error'))
      return
    }
    navigate(`/reset-password?identifier=${encodeURIComponent(identifier.trim())}`)
  }

  return (
    <div className="login-page">
      <div className="login-page__inner">
        <div className="login-card">
          <span className="login-card__logo">{t('forgotPassword.logo')}</span>
          <h1>{t('forgotPassword.title')}</h1>
          <form className="login-form" onSubmit={handleSubmit} noValidate>
            <div className="login-field">
              <label className="login-field__label" htmlFor="identifier">{t('forgotPassword.identifier')}</label>
              <input
                className={`login-field__input${touched && !identifier.trim() ? ' login-field__input--error' : ''}`}
                id="identifier"
                type="text"
                placeholder={t('forgotPassword.identifierPlaceholder')}
                value={identifier}
                onChange={(event) => setIdentifier(event.target.value)}
                onBlur={() => setTouched(true)}
              />
              {touched && !identifier.trim() && <span className="login-field__error">{t('login.required')}</span>}
            </div>
            <button className="login-form__submit" type="submit" disabled={!identifier.trim()}>{t('forgotPassword.submit')}</button>
          </form>
          {error && <p className="login-field__error">{error}</p>}
          <div className="login-card__links"><Link className="login-card__link" to="/login">{t('forgotPassword.back')}</Link></div>
        </div>
        {SHOW_AUTH_ILLUSTRATION && <img className="login-page__illustration" src="/img/login.png" alt="" />}
      </div>
    </div>
  )
}