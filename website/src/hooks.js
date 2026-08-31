import { useEffect } from 'react';

export function usePageSetup(pageClass) {
  useEffect(() => {
    document.body.className = pageClass;
    const rootClass = `${pageClass}-root`;
    document.documentElement.classList.add(rootClass);
    window.scrollTo(0, 0);
    const items = document.querySelectorAll('.reveal:not(.is-visible)');
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.14 });
    items.forEach((item) => observer.observe(item));

    const chapters = [...document.querySelectorAll('[data-scroll-chapter]')];
    const chapterObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        chapters.forEach((chapter) => chapter.classList.remove('is-current'));
        entry.target.classList.add('is-current');
      });
    }, { rootMargin: '-30% 0px -52%', threshold: 0 });
    chapters.forEach((chapter) => chapterObserver.observe(chapter));

    const storyObservers = [...document.querySelectorAll('[data-scroll-story]')].map((story) => {
      const steps = [...story.querySelectorAll('[data-scroll-step]')];
      const stepObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const activeIndex = entry.target.dataset.stepIndex;
          story.dataset.activeStep = activeIndex;
          steps.forEach((step) => step.classList.toggle('is-active', step === entry.target));
          story.querySelectorAll('[data-story-panel], [data-story-marker]').forEach((item) => {
            const itemIndex = item.dataset.storyPanel ?? item.dataset.storyMarker;
            item.classList.toggle('is-active', itemIndex === activeIndex);
          });
        });
      }, { rootMargin: '-38% 0px -48%', threshold: 0 });
      steps.forEach((step) => stepObserver.observe(step));
      return stepObserver;
    });

    return () => {
      document.documentElement.classList.remove(rootClass);
      observer.disconnect();
      chapterObserver.disconnect();
      storyObservers.forEach((storyObserver) => storyObserver.disconnect());
    };
  }, [pageClass]);
}
