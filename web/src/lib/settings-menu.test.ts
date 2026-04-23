import { describe, expect, it } from 'vitest';

import { getSettingsMenuItems, shouldShowAdminControls } from './settings-menu';

describe('settings menu permissions', () => {
    it('shows only login for anonymous users', () => {
        expect(getSettingsMenuItems(null)).toEqual([
            { label: 'Log In', href: '/login' },
        ]);
        expect(shouldShowAdminControls(null)).toBe(false);
    });

    it('shows only user settings for normal users', () => {
        expect(getSettingsMenuItems({ is_admin: false })).toEqual([
            { label: 'User Settings', href: '/settings/user' },
        ]);
        expect(shouldShowAdminControls({ is_admin: false })).toBe(false);
    });

    it('shows admin settings for admin users', () => {
        expect(getSettingsMenuItems({ is_admin: true })).toEqual([
            { label: 'User Settings', href: '/settings/user' },
            { label: 'Create User', href: '/settings/users' },
            { label: 'Library Management', href: '/settings/library' },
            { label: 'Scheduler', href: '/settings/scheduler' },
            { label: 'Media Quality', href: '/settings/media-quality' },
            { label: 'Network Renderers', href: '/renderers' },
            { label: 'Monitoring', href: '/settings/monitoring' },
        ]);
        expect(shouldShowAdminControls({ is_admin: true })).toBe(true);
    });
});
