import { useEffect, useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import Brand from './Brand';

export default function Nav({ demo = false }) {
  const [isFixed, setIsFixed] = useState(false);
  const [activeChapter, setActiveChapter] = useState('');

  useEffect(() => {
    let frame = 0;
    const chapters = [...document.querySelectorAll('[data-scroll-chapter]')];

    const updateNavigation = () => {
      frame = 0;
      const conversationComposer = document.querySelector('.product-preview-composer');
      const triggerPoint = conversationComposer
        ? conversationComposer.getBoundingClientRect().top + window.scrollY - 120
        : window.innerHeight;

      const chapterLine = window.innerHeight * 0.33;
      const currentChapter = chapters.find((chapter) => {
        const bounds = chapter.getBoundingClientRect();
        return bounds.top <= chapterLine && bounds.bottom > chapterLine;
      });
      setIsFixed(window.scrollY >= triggerPoint || Boolean(currentChapter));
      const nextChapter = currentChapter
        ? `${currentChapter.id}|${currentChapter.dataset.chapter}`
        : '';
      setActiveChapter(nextChapter);
    };

    const scheduleUpdate = () => {
      if (!frame) frame = window.requestAnimationFrame(updateNavigation);
    };

    updateNavigation();
    window.addEventListener('scroll', scheduleUpdate, { passive: true });
    window.addEventListener('resize', scheduleUpdate);

    return () => {
      window.removeEventListener('scroll', scheduleUpdate);
      window.removeEventListener('resize', scheduleUpdate);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  const [activeChapterId = '', activeChapterLabel = ''] = activeChapter.split('|');
  const [chapterNumber = '', chapterName = ''] = activeChapterLabel.split(' / ');

  return (
    <header className={`site-nav${demo ? ' demo-nav' : ''}${isFixed ? ' is-fixed' : ''}${activeChapterLabel ? ' has-chapter' : ''}`}>
      <Link to="/" aria-label="TikTok TechJam home"><Brand dark={isFixed} /></Link>
      {!demo && (
        <a
          className={`nav-chapter${isFixed && activeChapterLabel ? ' is-visible' : ''}`}
          href={activeChapterId ? `#${activeChapterId}` : undefined}
          aria-label={activeChapterLabel ? `Current chapter: ${activeChapterLabel}` : 'Current chapter'}
        >
          <span className="nav-chapter-copy" key={activeChapterLabel}>
            <small>{chapterNumber}</small>
            <strong>{chapterName}</strong>
          </span>
        </a>
      )}
      <nav aria-label="Main navigation">
        <NavLink className={({ isActive }) => `nav-link${isActive ? ' is-active' : ''}`} end to="/">Product</NavLink>
        <NavLink className={({ isActive }) => `nav-link${isActive ? ' is-active' : ''}`} to="/demo">Demo</NavLink>
        <Link className="nav-link" to="/#contact">Contact</Link>
      </nav>
    </header>
  );
}
