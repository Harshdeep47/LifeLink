import { Link } from 'react-router-dom'

import { EmptyPanel } from '../../components/ui.jsx'

export function NotFoundPage() {
  return (
    <EmptyPanel
      title="Page not found"
      message="The address you followed does not exist in LifeLink."
      action={<Link to="/" className="btn btn--primary">Back to home</Link>}
    />
  )
}
