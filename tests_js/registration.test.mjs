import assert from "node:assert/strict";
import test from "node:test";

import {
  REGISTRATION_PASSWORD_MAX_LENGTH,
  REGISTRATION_PASSWORD_MIN_LENGTH,
  registrationPayload,
  registrationValidationKey
} from "../frontend/registration.mjs";

const validRegistration = {
  firstName: "Anna",
  email: "anna@example.com",
  password: "correct-password",
  confirmPassword: "correct-password"
};

test("registration accepts the backend password bounds", () => {
  assert.equal(REGISTRATION_PASSWORD_MIN_LENGTH, 8);
  assert.equal(REGISTRATION_PASSWORD_MAX_LENGTH, 128);
  assert.equal(registrationValidationKey(validRegistration), null);
  assert.equal(registrationValidationKey({ ...validRegistration, password: "12345678", confirmPassword: "12345678" }), null);
  assert.equal(registrationValidationKey({ ...validRegistration, password: "a".repeat(128), confirmPassword: "a".repeat(128) }), null);
});

test("registration validates every required frontend field", () => {
  assert.equal(registrationValidationKey({ ...validRegistration, firstName: " " }), "register.validationName");
  assert.equal(registrationValidationKey({ ...validRegistration, email: "not-an-email" }), "register.validationEmail");
  assert.equal(registrationValidationKey({ ...validRegistration, password: "", confirmPassword: "" }), "register.validationPasswordRequired");
  assert.equal(registrationValidationKey({ ...validRegistration, password: "short", confirmPassword: "short" }), "register.validationPasswordLength");
  assert.equal(registrationValidationKey({ ...validRegistration, confirmPassword: "" }), "register.validationConfirmPassword");
});

test("registration rejects mismatched passwords", () => {
  assert.equal(
    registrationValidationKey({ ...validRegistration, confirmPassword: "different-password" }),
    "register.validationPasswordMismatch"
  );
});

test("registration payload contains only fields supported by the API", () => {
  assert.deepEqual(registrationPayload(validRegistration, "en"), {
    first_name: "Anna",
    email: "anna@example.com",
    password: "correct-password",
    language_code: "en"
  });
  assert.equal("confirm_password" in registrationPayload(validRegistration, "it"), false);
});
