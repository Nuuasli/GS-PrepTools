import type { ReactNode } from "react";

interface PageHeadingProps {
  label: string;
  title: string;
  description: string;
  action?: ReactNode;
}

export function PageHeading({
  label,
  title,
  description,
  action,
}: PageHeadingProps) {
  return (
    <div className="page-heading">
      <div className="min-w-0">
        <p className="page-heading-label">{label}</p>
        <h1>{title}</h1>
        <p className="page-heading-description">{description}</p>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
