export type Role = 'member' | 'moderator' | 'admin';
export interface User { id: string; username: string; display_name: string; role: Role; status: 'active' | 'disabled'; avatar_url: string | null; bio: string }
export interface ProfileResponse { user: User }
export interface Author { id: string; username: string | null; display_name?: string | null; avatar_url?: string | null }
export interface Thread { id: string; title: string; description: string; author: Author | null; tags: string[]; like_count: number; comment_count: number; liked_by_me: boolean; created_at: string; updated_at: string; is_edited: boolean }
export interface Page<T> { items: T[]; next_cursor: string | null }
export interface Reply { id: string; body: string | null; depth: number; author?: Author | null; deleted?: boolean; like_count?: number; liked_by_me?: boolean; reply_count?: number; parent_id?: string | null; is_continuation?: boolean; created_at?: string }
export interface Comment extends Reply { author: Author | null; like_count: number; reply_count: number; replies: Reply[]; replies_next_cursor: string | null }

export interface Notification { id: string; type: 'mention' | 'reply_thread' | 'reply_comment'; actor: { id: string; username: string }; thread_id: string; comment_id: string | null; read_at: string | null; created_at: string }
export interface SearchHit { type: 'thread' | 'comment'; id: string; thread_id: string; title: string | null; thread_title: string; snippet: string; author_username: string; created_at: string }
export interface Report { id: string; reporter_id: string; target_type: 'thread' | 'comment'; target_id: string; reason: string; note: string | null; status: 'open' | 'resolved' | 'dismissed'; created_at: string }
export interface AdminUser extends User { created_at: string; updated_at: string }
export interface Activity { id: string; actor_id: string; action: string; target_type: string; target_id: string; metadata: Record<string, unknown>; created_at: string }
