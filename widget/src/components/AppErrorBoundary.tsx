import { Component, type ErrorInfo, type ReactNode } from "react";
import { Icon } from "../icons";

type Props = {
  children: ReactNode;
};

type State = {
  error?: Error;
};

export class AppErrorBoundary extends Component<Props, State> {
  state: State = {};

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Expense tracker UI crashed", error, info.componentStack);
  }

  private recover = () => {
    window.openai?.setWidgetState?.({
      route: "/overview",
      period: "month",
      activityFilter: "all",
    });
    this.setState({ error: undefined });
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <main className="fatal-fallback" role="alert">
        <span className="fatal-fallback-icon">
          <Icon name="refresh" size={21} />
        </span>
        <div>
          <p className="section-kicker">VIEW INTERRUPTED</p>
          <h1>Let’s reload this screen.</h1>
          <p>
            Your expense data is safe. The embedded view hit a display error before it
            could finish rendering.
          </p>
        </div>
        <button className="primary-button" type="button" onClick={this.recover}>
          Reload tracker
        </button>
      </main>
    );
  }
}
