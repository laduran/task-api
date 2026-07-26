import type { AlpineComponent } from "alpinejs";

interface Me {
  authenticated: boolean;
  name?: string;
  email?: string;
  picture_url?: string | null;
}

interface AuthStoreData {
  loading: boolean;
  authenticated: boolean;
  name: string;
  pictureUrl: string | null;
  init(): void;
}

/**
 * Whether the visitor is signed in, checked once via GET /auth/me.
 *
 * Sign-in and sign-out are both plain full-page navigations (a link to
 * /auth/login, a <form method=post> to /auth/logout) — neither needs this
 * store's state to change client-side, since a real navigation re-runs
 * this check from scratch on the next page load.
 */
export function createAuthStore(): AlpineComponent<AuthStoreData> {
  return {
    loading: true,
    authenticated: false,
    name: "",
    pictureUrl: null,

    async init(): Promise<void> {
      try {
        const response = await fetch("/auth/me");
        const me = (await response.json()) as Me;
        this.authenticated = me.authenticated;
        this.name = me.name ?? "";
        this.pictureUrl = me.picture_url ?? null;
      } finally {
        this.loading = false;
      }
    },
  };
}
