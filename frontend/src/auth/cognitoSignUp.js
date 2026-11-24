/**
 * Cognito registration, confirmation and password recovery.
 *
 * Implemented with `fetch` against the Cognito Identity Provider JSON API
 * rather than by adding the AWS SDK. These particular operations — SignUp,
 * ConfirmSignUp, ResendConfirmationCode, ForgotPassword, ConfirmForgotPassword
 * — are unauthenticated for a public app client, so they need no request
 * signing and therefore no SDK. Pulling in `@aws-sdk/client-cognito-identity-provider`
 * to send five unsigned POSTs would add far more bundle weight and
 * supply-chain surface than it saves.
 *
 * Nothing secret is involved. The app client has no secret
 * (`GenerateSecret: false`, because a browser cannot keep one), and the client
 * id is a public identifier visible to anyone who signs in.
 *
 * Sign-*in* is deliberately NOT here. It stays with the hosted UI and
 * Authorization Code + PKCE in cognito.js: that flow already works, it keeps
 * the password exchange out of this origin entirely, and re-implementing it
 * with SRP would be both harder and worse.
 */

import { config } from './cognito.js'
import { PASSWORD_REQUIREMENTS } from './passwordPolicy.js'

const TARGET_PREFIX = 'AWSCognitoIdentityProviderService'

function endpoint(region) {
  return `https://cognito-idp.${region}.amazonaws.com/`
}

/** Region taken from the user pool id, which always starts with it. */
function regionFromPool(poolId) {
  const match = /^([a-z]{2}-[a-z]+-\d+)_/.exec(poolId ?? '')
  return match ? match[1] : 'ap-southeast-2'
}

/**
 * Turn a Cognito error into something worth showing a person.
 *
 * Cognito's messages are mostly usable, but a few are not: its password-policy
 * message is a regular expression, and `UserNotFoundException` on a password
 * reset would confirm whether an address is registered.
 */
function friendlyError(type, message) {
  const name = (type ?? '').split('#').pop()
  switch (name) {
    case 'UsernameExistsException':
      return 'An account with that email address already exists. Try signing in instead.'
    case 'InvalidPasswordException':
      return `That password does not meet the requirements: ${PASSWORD_REQUIREMENTS.charAt(0).toLowerCase()}${PASSWORD_REQUIREMENTS.slice(1)}`
    case 'InvalidParameterException':
      return message?.includes('password')
        ? 'That password does not meet the requirements.'
        : (message ?? 'One of the details provided was not valid.')
    case 'CodeMismatchException':
      return 'That code is not correct. Check it and try again.'
    case 'ExpiredCodeException':
      return 'That code has expired. Request a new one.'
    case 'LimitExceededException':
    case 'TooManyRequestsException':
      return 'Too many attempts. Please wait a few minutes and try again.'
    case 'UserNotFoundException':
      // Deliberately vague: confirming whether an address is registered is
      // an account-enumeration gift.
      return 'If that email address has an account, a reset code has been sent.'
    case 'NotAuthorizedException':
      return message ?? 'That request was not permitted.'
    default:
      return message ?? 'Something went wrong. Please try again.'
  }
}

async function call(action, payload) {
  const { clientId, poolId } = { clientId: config().clientId, poolId: config().poolId }
  const region = regionFromPool(poolId) || 'ap-southeast-2'
  if (!clientId) throw new Error('Registration is not configured in this build.')

  const response = await fetch(endpoint(region), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': `${TARGET_PREFIX}.${action}`,
    },
    body: JSON.stringify({ ClientId: clientId, ...payload }),
  })

  const text = await response.text()
  let body = {}
  try {
    body = text ? JSON.parse(text) : {}
  } catch {
    /* non-JSON body */
  }

  if (!response.ok) {
    throw new Error(friendlyError(body.__type, body.message))
  }
  return body
}

/**
 * Register an account.
 *
 * The display name goes into the standard `name` attribute, which is what the
 * API later reads when it provisions the LifeLink profile. Without it a new
 * user's name is their Cognito subject uuid.
 *
 * `requestedAccountType` is recorded as a custom-free hint only — it grants
 * nothing. Institutional roles are assigned by an administrator after
 * verification; see the organization access request on the profile page.
 */
export async function signUp({ email, password, fullName }) {
  const result = await call('SignUp', {
    Username: email,
    Password: password,
    UserAttributes: [
      { Name: 'email', Value: email },
      { Name: 'name', Value: fullName },
    ],
  })
  return {
    userConfirmed: Boolean(result.UserConfirmed),
    // Where the code went, so the page can say "check your email" accurately
    // rather than guessing.
    destination: result.CodeDeliveryDetails?.Destination ?? email,
  }
}

/** Confirm with the emailed one-time code. */
export async function confirmSignUp({ email, code }) {
  await call('ConfirmSignUp', { Username: email, ConfirmationCode: code })
  return true
}

/** Send another confirmation code. */
export async function resendConfirmationCode({ email }) {
  const result = await call('ResendConfirmationCode', { Username: email })
  return result.CodeDeliveryDetails?.Destination ?? email
}

/** Begin a password reset. */
export async function forgotPassword({ email }) {
  const result = await call('ForgotPassword', { Username: email })
  return result.CodeDeliveryDetails?.Destination ?? email
}

/** Complete a password reset with the emailed code. */
export async function confirmForgotPassword({ email, code, password }) {
  await call('ConfirmForgotPassword', {
    Username: email,
    ConfirmationCode: code,
    Password: password,
  })
  return true
}

/** Whether registration can work in this build. */
export function isSignUpConfigured() {
  return Boolean(config().clientId)
}
