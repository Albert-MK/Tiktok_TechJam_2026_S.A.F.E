import { Link } from 'react-router-dom';
import Brand from './Brand';

export default function Footer() {
  return (
    <footer id="contact" className="site-footer">
      <div className="footer-brand"><Link to="/"><Brand dark /></Link><p>Conversational shopping, built for the hackathon.</p></div>
      <div className="footer-group"><p>Explore</p><Link to="/">Product</Link><Link to="/demo">Demo</Link></div>
      <div className="footer-group"><p>Project</p><span>GitHub · coming soon</span><span>Devpost · coming soon</span></div>
      <div className="footer-bottom"><span>© TikTok TechJam team</span><span>Built with curiosity in Singapore.</span></div>
    </footer>
  );
}
