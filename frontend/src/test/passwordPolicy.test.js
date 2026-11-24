/**
 * The password policy, and whether it matches the deployed user pool.
 *
 * The defect this guards: the sign-up form's validator carried the comment
 * "mirrors the user pool's policy" while requiring 8 characters and no
 * symbol. The deployed policy requires **12 and a symbol**. So `Password1`
 * satisfied every rule the page stated, was sent to Cognito, and was refused.
 * The user had done nothing wrong.
 *
 * The last test is the important one: it reads
 * `infrastructure/template.yaml` and asserts the constants agree with it, so
 * changing the policy on one side alone fails the suite instead of reaching a
 * user.
 */
import { existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  MIN_LENGTH,
  PASSWORD_REQUIREMENTS,
  SYMBOLS,
  passwordProblem,
  passwordProblems,
} from '../auth/passwordPolicy.js'

/** A password satisfying every rule, for one-rule-at-a-time tests. */
const GOOD = 'Correct-Horse9'

describe('passwordProblem', () => {
  it('accepts a password meeting every rule', () => {
    expect(passwordProblem(GOOD)).toBeNull()
  })

  it('rejects the password that exposed the bug', () => {
    // 9 characters, no symbol: passed the old check, refused by Cognito.
    expect(passwordProblem('Password1')).not.toBeNull()
  })

  it('requires the full minimum length, not a shorter one', () => {
    expect(passwordProblem('Short1!a')).toBe(`Use at least ${MIN_LENGTH} characters.`)
    // Exactly one short.
    const justShort = `Aa1!${'b'.repeat(MIN_LENGTH - 5)}`
    expect(justShort.length).toBe(MIN_LENGTH - 1)
    expect(passwordProblem(justShort)).toContain(`${MIN_LENGTH} characters`)
  })

  it('accepts a password of exactly the minimum length', () => {
    const exact = `Aa1!${'b'.repeat(MIN_LENGTH - 4)}`
    expect(exact.length).toBe(MIN_LENGTH)
    expect(passwordProblem(exact)).toBeNull()
  })

  it('requires a lower-case letter', () => {
    expect(passwordProblem('CORRECT-HORSE9')).toBe('Include a lower-case letter.')
  })

  it('requires an upper-case letter', () => {
    expect(passwordProblem('correct-horse9')).toBe('Include an upper-case letter.')
  })

  it('requires a number', () => {
    expect(passwordProblem('Correct-Horsey')).toBe('Include a number.')
  })

  it('requires a symbol — the rule that was missing entirely', () => {
    expect(passwordProblem('CorrectHorse99')).toBe(
      'Include a symbol, such as ! ? # or @.',
    )
  })

  it.each([...'!@#$%^&*()_+-=[]{}|;:,.<>?/'])(
    'accepts %s as a symbol',
    (symbol) => {
      const candidate = `Aa1${symbol}${'b'.repeat(MIN_LENGTH)}`
      expect(passwordProblem(candidate)).toBeNull()
    },
  )

  it('treats a missing or non-string password as failing, not as passing', () => {
    expect(passwordProblem(undefined)).not.toBeNull()
    expect(passwordProblem(null)).not.toBeNull()
    expect(passwordProblem('')).not.toBeNull()
    expect(passwordProblem(12345678901234)).not.toBeNull()
  })

  it('reports the length rule first, so the advice is the most useful one', () => {
    expect(passwordProblem('')).toContain(`${MIN_LENGTH} characters`)
  })
})

describe('passwordProblems', () => {
  it('lists every unmet rule', () => {
    const problems = passwordProblems('abc')
    expect(problems.length).toBeGreaterThan(1)
    expect(problems.some((p) => p.includes(`${MIN_LENGTH} characters`))).toBe(true)
    expect(problems.some((p) => p.includes('upper-case'))).toBe(true)
    expect(problems.some((p) => p.includes('symbol'))).toBe(true)
  })

  it('is empty for a good password', () => {
    expect(passwordProblems(GOOD)).toEqual([])
  })
})

describe('PASSWORD_REQUIREMENTS', () => {
  it('states the real minimum length', () => {
    expect(PASSWORD_REQUIREMENTS).toContain(String(MIN_LENGTH))
  })

  it('mentions the symbol requirement, which the old wording omitted', () => {
    expect(PASSWORD_REQUIREMENTS.toLowerCase()).toContain('symbol')
  })

  it('no longer tells the user eight characters will do', () => {
    expect(PASSWORD_REQUIREMENTS).not.toContain('8 characters')
  })
})

describe('agreement with the deployed user pool', () => {
  /**
   * Reads the template rather than trusting a comment. This is the test that
   * would have caught the original defect.
   */
  function template() {
    let dir = process.cwd()
    for (let depth = 0; depth < 4; depth += 1) {
      const candidate = join(dir, 'infrastructure', 'template.yaml')
      if (existsSync(candidate)) return readFileSync(candidate, 'utf8')
      dir = resolve(dir, '..')
    }
    throw new Error('could not locate infrastructure/template.yaml')
  }

  const text = template()
  const policy = text.slice(text.indexOf('PasswordPolicy:'))

  it('finds the user pool password policy in the template', () => {
    expect(policy).toContain('MinimumLength:')
  })

  it('uses the same minimum length as the user pool', () => {
    const declared = Number(/MinimumLength:\s*(\d+)/.exec(policy)?.[1])
    expect(declared).toBe(MIN_LENGTH)
  })

  it.each([
    ['RequireLowercase', 'abcdefghijkl'],
    ['RequireUppercase', 'ABCDEFGHIJKL'],
    ['RequireNumbers', '123456789012'],
  ])('enforces %s because the user pool does', (flag, onlyThatClass) => {
    const required = new RegExp(`${flag}:\\s*true`).test(policy)
    expect(required).toBe(true)
    // A password of only this character class must still be refused, which
    // proves the other required classes are enforced on our side too.
    expect(passwordProblem(onlyThatClass)).not.toBeNull()
  })

  it('enforces RequireSymbols because the user pool does', () => {
    expect(/RequireSymbols:\s*true/.test(policy)).toBe(true)
    // Satisfies everything except the symbol rule.
    expect(passwordProblem('CorrectHorse99')).toContain('symbol')
  })

  it('uses a symbol set, not a loose non-word match', () => {
    // `\W` would accept characters Cognito does not count as symbols. The
    // explicit set is narrower, which is the safe direction for a pre-flight
    // check: it never promises a password Cognito would refuse.
    expect(SYMBOLS.length).toBeGreaterThan(10)
    expect(passwordProblem(`Aa1${'é'}${'b'.repeat(MIN_LENGTH)}`)).toContain('symbol')
  })
})
