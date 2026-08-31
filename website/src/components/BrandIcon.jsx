export default function BrandIcon({ className = '', tone = 'light' }) {
  return (
    <span className={`shopturn-icon ${className} ${tone}`.trim()} aria-hidden="true" />
  );
}
