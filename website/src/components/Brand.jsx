import BrandIcon from './BrandIcon';

export default function Brand({ dark = false }) {
  return (
    <span className={`brand${dark ? ' dark' : ''}`}>
      <BrandIcon className="brand-mark" tone={dark ? 'dark' : 'light'} />
      <span>TikTok TechJam</span>
    </span>
  );
}
