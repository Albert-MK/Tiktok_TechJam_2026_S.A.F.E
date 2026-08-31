import curiousIcon from '../../bloub-squircle-curieux-bleu-anime.svg';
import surprisedIcon from '../../bloub-squircle-surpris-bleu-anime.svg';

const stateIcons = {
  thinking: curiousIcon,
  answered: surprisedIcon,
};

export default function ChatStateIcon({ state = 'answered', className = '' }) {
  return (
    <img
      className={`chat-state-icon ${className}`.trim()}
      src={stateIcons[state] ?? stateIcons.answered}
      alt=""
      aria-hidden="true"
    />
  );
}
