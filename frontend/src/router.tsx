import { createBrowserRouter, Navigate } from 'react-router-dom';
import App from './App';
import ChatPage from './pages/ChatPage';
import SplashPage from './pages/SplashPage';
import NotFoundPage from './pages/NotFoundPage';

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      {
        index: true,
        element: <Navigate to="/splash" replace />,
      },
      {
        path: 'splash',
        element: <SplashPage />,
      },
      {
        path: 'chat',
        element: <ChatPage />,
      },
      // 兜底404路由
      {
        path: '*',
        element: <NotFoundPage />,
      },
    ],
  },
]);

export default router;
