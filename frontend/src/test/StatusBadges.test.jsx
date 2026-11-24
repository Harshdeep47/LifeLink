/**
 * Badge tests.
 *
 * These assert the presentation rules the specification treats as safety
 * properties, not cosmetics: UNKNOWN must never render as zero or as
 * unavailable, and freshness must never be shown without verification beside it.
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import {
  AvailabilityBadge,
  DataQuality,
  FreshnessBadge,
  PriorityBadge,
  VerificationBadge,
} from '../components/StatusBadges.jsx'

describe('AvailabilityBadge', () => {
  it('shows the unit count when stock is genuinely available', () => {
    render(<AvailabilityBadge state="AVAILABLE" units={12} />)
    expect(screen.getByText('Available')).toBeInTheDocument()
    expect(screen.getByText('12 units')).toBeInTheDocument()
  })

  it('uses the singular for one unit', () => {
    render(<AvailabilityBadge state="AVAILABLE" units={1} />)
    expect(screen.getByText('1 unit')).toBeInTheDocument()
  })

  it('renders UNKNOWN as "Not reported", never as a zero count', () => {
    render(<AvailabilityBadge state="UNKNOWN" units={0} />)
    expect(screen.getByText('Not reported')).toBeInTheDocument()
    expect(screen.queryByText(/0 units/)).not.toBeInTheDocument()
  })

  it('distinguishes "none in stock" from "not reported"', () => {
    const { unmount } = render(<AvailabilityBadge state="UNAVAILABLE" units={0} />)
    expect(screen.getByText('None in stock')).toBeInTheDocument()
    unmount()

    render(<AvailabilityBadge state="UNKNOWN" />)
    expect(screen.getByText('Not reported')).toBeInTheDocument()
    expect(screen.queryByText('None in stock')).not.toBeInTheDocument()
  })

  it('treats a missing state as unknown rather than available', () => {
    render(<AvailabilityBadge state={undefined} />)
    expect(screen.getByText('Not reported')).toBeInTheDocument()
  })

  it('shows partial availability distinctly', () => {
    render(<AvailabilityBadge state="PARTIAL" units={3} />)
    expect(screen.getByText('Partial')).toBeInTheDocument()
    expect(screen.getByText('3 units')).toBeInTheDocument()
  })
})

describe('FreshnessBadge', () => {
  it.each([
    ['FRESH', 'Fresh'],
    ['AGING', 'Aging'],
    ['STALE', 'Stale'],
    ['OUTDATED', 'Outdated'],
  ])('renders %s as %s', (level, label) => {
    render(<FreshnessBadge level={level} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('renders a missing level as "No update time", not as fresh', () => {
    render(<FreshnessBadge level={undefined} />)
    expect(screen.getByText('No update time')).toBeInTheDocument()
  })
})

describe('VerificationBadge', () => {
  it('states plainly when nothing has been verified', () => {
    render(<VerificationBadge status="UNVERIFIED" />)
    expect(screen.getByText('Not verified')).toBeInTheDocument()
  })

  it('distinguishes expired verification from never verified', () => {
    render(<VerificationBadge status="VERIFICATION_EXPIRED" />)
    expect(screen.getByText('Verification expired')).toBeInTheDocument()
  })

  it('defaults to unverified for an unknown status', () => {
    render(<VerificationBadge status="SOMETHING_ELSE" />)
    expect(screen.getByText('Not verified')).toBeInTheDocument()
  })
})

describe('DataQuality', () => {
  it('always shows freshness and verification together', () => {
    render(<DataQuality freshness="FRESH" verification="UNVERIFIED" />)
    // The combination that matters: recently updated, but nobody checked it.
    expect(screen.getByText('Fresh')).toBeInTheDocument()
    expect(screen.getByText('Not verified')).toBeInTheDocument()
  })

  it('shows both even when they agree', () => {
    render(<DataQuality freshness="FRESH" verification="VERIFIED" />)
    expect(screen.getByText('Fresh')).toBeInTheDocument()
    expect(screen.getByText('Independently verified')).toBeInTheDocument()
  })
})

describe('PriorityBadge', () => {
  it('maps internal codes to hospital-facing words', () => {
    const { unmount } = render(<PriorityBadge priority="P1" />)
    expect(screen.getByText('Critical')).toBeInTheDocument()
    unmount()

    render(<PriorityBadge priority="P3" />)
    expect(screen.getByText('Scheduled')).toBeInTheDocument()
  })

  it('says "Not certified" when no priority exists rather than guessing one', () => {
    render(<PriorityBadge priority={null} />)
    expect(screen.getByText('Not certified')).toBeInTheDocument()
  })
})
