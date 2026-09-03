export const REGISTRATION_PASSWORD_MIN_LENGTH = 8;
export const REGISTRATION_PASSWORD_MAX_LENGTH = 128;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function registrationValidationKey({ firstName, email, password, confirmPassword }) {
  if (!firstName.trim()) return "register.validationName";
  if (!EMAIL_PATTERN.test(email.trim())) return "register.validationEmail";
  if (!password) return "register.validationPasswordRequired";
  if (password.length < REGISTRATION_PASSWORD_MIN_LENGTH || password.length > REGISTRATION_PASSWORD_MAX_LENGTH) {
    return "register.validationPasswordLength";
  }
  if (!confirmPassword) return "register.validationConfirmPassword";
  if (password !== confirmPassword) return "register.validationPasswordMismatch";
  return null;
}

export function registrationPayload({ firstName, email, password }, languageCode) {
  return {
    first_name: firstName.trim(),
    email: email.trim(),
    password,
    language_code: languageCode
  };
}
