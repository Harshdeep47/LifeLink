/**
 * The Cognito user pool's password policy, in one place.
 *
 * ## Why this file exists
 *
 * The rules were previously written out three times — in the sign-up form's
 * validation function, in that form's hint text, and in the error-message
 * translation in `cognitoSignUp.js` — and all three disagreed with the user
 * pool. The validator's comment said "mirrors the user pool's policy"; it did
 * not. It required 8 characters and no symbol, while the deployed policy
 * requires **12 characters and a symbol**.
 *
 * The consequence was a broken registration: `Password1` passed every
 * client-side check, was sent to Cognito, and came back refused. The user had
 * satisfied every rule the page stated.
 *
 * Three copies of a rule is three chances to be wrong, so there is now one.
 *
 * ## Keeping it true
 *
 * These constants mirror `UserPool.Policies.PasswordPolicy` in
 * `infrastructure/template.yaml`. A test asserts the two agree by reading the
 * template, so changing the policy in one place and not the other fails the
 * suite rather than reaching a user.
 */

/** Mirrors `MinimumLength` in the template. */
export const MIN_LENGTH = 12

/**
 * Mirrors the `Require*` flags in the template.
 *
 * Cognito's symbol set, from its own documentation. Listed explicitly rather
 * than tested with `\W`, because `\W` would accept characters Cognito does not
 * count as symbols and reject none that it does — the wrong direction for a
 * pre-flight check.
 */
export const SYMBOLS = '^$*.[]{}()?"!@#%&/\\,><\':;|_~`=+- '

const RULES = [
  {
    test: (p) => p.length >= MIN_LENGTH,
    message: `Use at least ${MIN_LENGTH} characters.`,
  },
  { test: (p) => /[a-z]/.test(p), message: 'Include a lower-case letter.' },
  { test: (p) => /[A-Z]/.test(p), message: 'Include an upper-case letter.' },
  { test: (p) => /\d/.test(p), message: 'Include a number.' },
  {
    test: (p) => [...p].some((ch) => SYMBOLS.includes(ch)),
    message: 'Include a symbol, such as ! ? # or @.',
  },
]

/**
 * The first unmet rule, or null when the password satisfies all of them.
 *
 * Returns one message rather than all of them: a list of five complaints
 * about an empty field is noise, and the user is typing.
 */
export function passwordProblem(password) {
  const value = typeof password === 'string' ? password : ''
  for (const rule of RULES) {
    if (!rule.test(value)) return rule.message
  }
  return null
}

/** Every unmet rule, for a checklist that updates as the user types. */
export function passwordProblems(password) {
  const value = typeof password === 'string' ? password : ''
  return RULES.filter((rule) => !rule.test(value)).map((rule) => rule.message)
}

/** One sentence describing the policy, for hint text and error messages. */
export const PASSWORD_REQUIREMENTS =
  `At least ${MIN_LENGTH} characters, with upper and lower case letters, ` +
  'a number and a symbol.'
