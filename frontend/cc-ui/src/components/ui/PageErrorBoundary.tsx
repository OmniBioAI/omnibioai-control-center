import { Component, type ErrorInfo, type ReactNode } from 'react'
import ErrorState from './ErrorState'

interface Props { children: ReactNode }
interface State { failed: boolean }

/** Keeps one page's render error inside that page. Without it, an
 * unexpected API response shape blanked the whole console, sidebar and
 * top bar included, until a full reload. AppShell keys it by the active
 * page, so navigating elsewhere always starts from a clean state. */
export default class PageErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Admin page failed to render', error, info.componentStack)
  }

  render() {
    if (this.state.failed) {
      return (
        <ErrorState
          message="This page couldn't be displayed. The rest of the console still works; try again, or pick another page."
          onRetry={() => this.setState({ failed: false })}
        />
      )
    }
    return this.props.children
  }
}
