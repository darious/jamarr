export interface SettingsMenuUser {
    is_admin?: boolean;
}

export interface SettingsMenuItem {
    label: string;
    href: string;
}

export function getSettingsMenuItems(user: SettingsMenuUser | null | undefined): SettingsMenuItem[] {
    if (!user) {
        return [{ label: 'Log In', href: '/login' }];
    }

    const items: SettingsMenuItem[] = [
        { label: 'User Settings', href: '/settings/user' },
    ];

    if (user.is_admin) {
        items.push(
            { label: 'Create User', href: '/settings/users' },
            { label: 'Library Management', href: '/settings/library' },
            { label: 'Scheduler', href: '/settings/scheduler' },
            { label: 'Media Quality', href: '/settings/media-quality' },
            { label: 'Network Renderers', href: '/renderers' },
        );
    }

    return items;
}

export function shouldShowAdminControls(user: SettingsMenuUser | null | undefined): boolean {
    return Boolean(user?.is_admin);
}
