import React from 'react';

type ToastProps = {
  message: string | null;
};

export default function Toast({ message }: ToastProps) {
  if (!message) {
    return null;
  }
  return (
    <div className="toast" role="status" aria-live="polite">
      {message}
    </div>
  );
}
