import BackgroundVideo from './BackgroundVideo';

export default function HeroBackground() {
  return (
    <BackgroundVideo
      className="hero-background-media"
      src="/assets/shoptun-product-hero.mp4?v=frontend-4"
      poster="/assets/shoptun-product-hero-poster.jpg?v=frontend-4"
    />
  );
}
