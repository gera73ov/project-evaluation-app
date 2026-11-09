/** FE-010 · маршрут «/»: «Мои оценки» для вошедшего пользователя. */
import { useSession } from '../../app/session';
import { HomePage } from './HomePage';

export function HomeRoute() {
  const { session } = useSession();
  return session.state === 'ready' ? <HomePage me={session.me} /> : null;
}
