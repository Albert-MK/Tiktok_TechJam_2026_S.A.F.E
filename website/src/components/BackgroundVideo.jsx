import { useEffect, useRef } from 'react';

export default function BackgroundVideo({ className, src, poster }) {
  const videoRef = useRef(null);

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const updatePlayback = () => {
      const video = videoRef.current;
      if (!video) return;
      if (media.matches) {
        video.pause();
        video.currentTime = 0;
      } else {
        video.play().catch(() => {});
      }
    };
    updatePlayback();
    media.addEventListener('change', updatePlayback);
    return () => media.removeEventListener('change', updatePlayback);
  }, []);

  return (
    <video ref={videoRef} className={className} autoPlay muted loop playsInline preload="metadata" poster={poster} aria-hidden="true">
      <source src={src} type="video/mp4" />
    </video>
  );
}
