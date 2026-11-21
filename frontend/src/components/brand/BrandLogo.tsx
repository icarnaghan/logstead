import { Component, type ErrorInfo, type ReactNode } from "react";
import { Logo, type LogoProps } from "./Logo";
import { WordmarkFallback } from "./WordmarkFallback";

/**
 * Single switch for the brand mark. To fall back to text everywhere, change
 * BrandMark below to WordmarkFallback (Requirement 16.5).
 */
const BrandMark = (props: LogoProps) => <Logo {...props} />;

class LogoBoundary extends Component<{ children: ReactNode; decorative?: boolean }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn("Logo failed to render; using text fallback.", error, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return this.props.decorative ? (
        <span aria-hidden="true" className="text-xl font-semibold tracking-tight text-fg">
          logstead
        </span>
      ) : (
        <WordmarkFallback />
      );
    }
    return this.props.children;
  }
}

export function BrandLogo(props: LogoProps) {
  return (
    <LogoBoundary decorative={props.decorative}>
      <BrandMark {...props} />
    </LogoBoundary>
  );
}
