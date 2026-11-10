import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./pages/login/login.component').then(m => m.LoginComponent),
  },
  {
    path: '',
    canActivate: [authGuard],
    children: [
      {
        path: '',
        loadComponent: () => import('./pages/dashboard/dashboard.component').then(m => m.DashboardComponent),
      },
      {
        path: 'users',
        loadComponent: () => import('./pages/users/users.component').then(m => m.UsersComponent),
      },
      {
        path: 'users/:id',
        loadComponent: () => import('./pages/user-detail/user-detail.component').then(m => m.UserDetailComponent),
      },
      {
        path: 'audit',
        loadComponent: () => import('./pages/audit/audit.component').then(m => m.AuditComponent),
      },
      {
        path: 'features',
        loadComponent: () => import('./pages/features/features.component').then(m => m.FeaturesComponent),
      },
      {
        path: 'health',
        loadComponent: () => import('./pages/health/health.component').then(m => m.HealthComponent),
      },
      {
        path: 'announcements',
        loadComponent: () => import('./pages/announcements/announcements.component').then(m => m.AnnouncementsComponent),
      },
      {
        path: 'quotas',
        loadComponent: () => import('./pages/quotas/quotas.component').then(m => m.QuotasComponent),
      },
      {
        path: 'sharing',
        loadComponent: () => import('./pages/sharing/sharing.component').then(m => m.SharingComponent),
      },
      {
        path: 'analytics',
        loadComponent: () => import('./pages/analytics/analytics.component').then(m => m.AnalyticsComponent),
      },
      {
        path: 'incidents',
        loadComponent: () => import('./pages/incidents/incidents.component').then(m => m.IncidentsComponent),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
