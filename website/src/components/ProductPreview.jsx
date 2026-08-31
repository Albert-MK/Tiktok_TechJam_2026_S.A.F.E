import { Link } from 'react-router-dom';
import animatedShoppingIcon from '../../bloub-squircle-attentif-bleu-anime.svg';

export default function ProductPreview() {
  return (
    <div className="hero-product-shell product-demo-preview liquid-glass reveal is-visible" aria-label="Preview of the TikTok TechJam conversation interface">
      <Link className="new-chat-button product-preview-new-chat" to="/demo">New conversation</Link>

      <div className="product-preview-welcome">
        <img className="product-preview-icon" src={animatedShoppingIcon} alt="" aria-hidden="true" />
        <p className="eyebrow">Conversational shopping</p>
        <h2>Start with a message.</h2>
        <p>Tell TikTok TechJam what you need. Continue naturally as your preferences change.</p>
      </div>

      <Link className="product-preview-composer" to="/demo" aria-label="Open the TikTok TechJam conversation demo">
        <span>Message TikTok TechJam…</span>
        <span className="product-preview-send" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="m5 12 14-7-4 14-3-6-7-1Z" /></svg>
        </span>
      </Link>
    </div>
  );
}
