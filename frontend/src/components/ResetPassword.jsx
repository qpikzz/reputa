import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import { postJSON } from '../api'
import { PASSWORD_RULES, SHOW_AUTH_ILLUSTRATION } from '../constants/auth'
import './Login.css'

export default function ResetPassword() {
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [identifier, setIdentifier] = useState(searchParams.get('identifier') || '')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [touched, setTouched] = useState({})
  const [error, setError] = useState('')
  const passwordChecks = Object.fromEntries(PASSWORD_RULES.map((rule) => [rule.key, rule.test(password)]))
  const passwordValid = PASSWORD_RULES.every((rule) => rule.test(password))
  const formValid = identifier.trim() && code.trim() && passwordValid && password === passwordConfirm

  async function handleSubmit(event) {
    event.preventDefault()
    setTouched({ identifier: true, code: true, password: true, passwordConfirm: true })
    if (!formValid) return

    setError('')
    const result = await postJSON('/api/auth/password-reset/confirm', {
      identifier: identifier.trim(), code: code.trim(), password,
    })
    if (!result.ok) {
      setError(result.error || t('resetPassword.error'))
      return
    }
    navigate('/login')
  }

  return (
    <div className="login-page">
      <div className="login-page__inner">
        <div className="login-card">
          <span className="login-card__logo">{t('resetPassword.logo')}</span>
          <h1>{t('resetPassword.title')}</h1>
          <form className="login-form" onSubmit={handleSubmit} noValidate>
            <div className="login-field">
              <label className="login-field__label" htmlFor="identifier">{t('resetPassword.identifier')}</label>
              <input className="login-field__input" id="identifier" value={identifier} onChange={(event) => setIdentifier(event.target.value)} placeholder={t('resetPassword.identifierPlaceholder')} />
            </div>
            <div className="login-field">
              <label className="login-field__label" htmlFor="code">{t('resetPassword.code')}</label>
              <input className="login-field__input" id="code" value={code} onChange={(event) => setCode(event.target.value)} placeholder={t('resetPassword.codePlaceholder')} maxLength="6" />
            </div>
            <div className="login-field">
              <label className="login-field__label" htmlFor="password">{t('resetPassword.password')}</label>
              <input className={`login-field__input${touched.password && !passwordValid ? ' login-field__input--error' : ''}`} id="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder={t('resetPassword.passwordPlaceholder')} />
              {touched.password && <div className="login-field__error">{PASSWORD_RULES.filter((rule) => !passwordChecks[rule.key]).map((rule) => t(`resetPassword.passwordRules.${rule.key}`)).join('; ')}</div>}
            </div>
            <div className="login-field">
              <label className="login-field__label" htmlFor="passwordConfirm">{t('resetPassword.passwordConfirm')}</label>
              <input className={`login-field__input${touched.passwordConfirm && password !== passwordConfirm ? ' login-field__input--error' : ''}`} id="passwordConfirm" type="password" value={passwordConfirm} onChange={(event) => setPasswordConfirm(event.target.value)} />
              {touched.passwordConfirm && password !== passwordConfirm && <span className="login-field__error">{t('resetPassword.passwordMismatch')}</span>}
            </div>
            <button className="login-form__submit" type="submit" disabled={!formValid}>{t('resetPassword.submit')}</button>
          </form>
          {error && <p className="login-field__error">{error}</p>}
          <div className="login-card__links"><Link className="login-card__link" to="/login">{t('resetPassword.back')}</Link></div>
        </div>
        {SHOW_AUTH_ILLUSTRATION && <img className="login-page__illustration" src="/img/login.png" alt="" />}
      </div>
    </div>
  )
}