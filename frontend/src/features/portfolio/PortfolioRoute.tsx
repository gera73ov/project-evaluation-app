/** FE-050 · маршрут «/portfolio»: портфель для вошедшего руководителя пресейла. */
import { useSession } from '../../app/session';
import { PortfolioPage } from './PortfolioPage';

export function PortfolioRoute() {
  const { session } = useSession();
  return session.state === 'ready' ? <PortfolioPage me={session.me} /> : null;
}
