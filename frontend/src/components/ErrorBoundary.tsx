// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { Component } from "react";
import type { ReactNode } from "react";

interface Props { children: ReactNode }
interface State { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="fixed inset-0 bg-page-bg flex items-center justify-center p-8">
          <div className="max-w-lg text-center space-y-4">
            <p className="text-white/70 text-xs font-mono uppercase tracking-widest">Failed to load</p>
            <p className="text-white text-sm font-mono break-all">{this.state.error.message}</p>
            <p className="text-white/60 text-xs">
              Please share this error — it helps diagnose browser compatibility issues.
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
