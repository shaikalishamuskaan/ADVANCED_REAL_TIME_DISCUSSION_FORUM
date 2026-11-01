import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from '../App';
import { AuthProvider } from '../auth/AuthProvider';
import { setSession } from '../lib/api';
import type { Role } from '../lib/types';
import { SecretReceipt } from '../components/ui';

const person = {id:'user-1',username:'alice',display_name:'Alice',role:'member' as Role,status:'active',bio:'Hello',avatar_url:null};
const thread = {id:'thread-1',title:'A thoughtful question',description:'Discussion body',author:{id:'user-1',username:'alice',display_name:'Alice'},tags:['python'],like_count:0,liked_by_me:false,comment_count:1,created_at:'2026-11-01T10:00:00Z',updated_at:'2026-11-01T10:00:00Z',is_edited:false};
const comment = {id:'comment-1',body:'An existing answer',depth:1,author:thread.author,like_count:0,liked_by_me:false,reply_count:0,replies:[],replies_next_cursor:null};
const json=(data:unknown,status=200)=>new Response(status===204?null:JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
type Handler=(path:string,options:RequestInit)=>Response|undefined;
function app(path:string,handler:Handler=()=>undefined,role:Role='member'){
  const profile={...person,role};
  const fetcher=vi.fn((path:string,options:RequestInit={})=>Promise.resolve(handler(path,options) || (
    path==='/api/auth/refresh'?json({access_token:'token'}):path==='/api/users/me'?json({user:profile}):path==='/api/notifications/unread-count'?json({unread_count:0}):path==='/api/forum/threads/thread-1'?json(thread):path==='/api/forum/threads/thread-1/comments'?json({items:[comment],next_cursor:null}):path.startsWith('/api/forum/threads')?json({items:[thread],next_cursor:null}):json({},404)
  )));
  vi.stubGlobal('fetch',fetcher);
  const cache=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});
  render(<QueryClientProvider client={cache}><MemoryRouter initialEntries={[path]}><AuthProvider><App/></AuthProvider></MemoryRouter></QueryClientProvider>);
  return {fetcher,cache};
}
const body=(options:RequestInit)=>JSON.parse(String(options.body));
beforeEach(()=>{setSession(null);});

it('corrects privileged controls when the server reports a stale role',async()=>{
 let profiles=0;app('/moderation',(path)=>path==='/api/users/me'?json({user:{...person,role:++profiles===1?'moderator':'member'}}):path.startsWith('/api/forum/moderation/reports')?json({detail:{error:{code:'insufficient_role',message:'Your role changed.'}}},403):undefined,'moderator');
 expect(await screen.findByText('This page is not available for your role.')).toBeInTheDocument();expect(screen.queryByRole('link',{name:'Reports'})).not.toBeInTheDocument();expect(profiles).toBe(2);
});
it('keeps a one-time code usable when clipboard access is unavailable',async()=>{
 const action=userEvent.setup();Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined});const done=vi.fn();render(<SecretReceipt code="TEST-ONLY-CODE" notice="Save it once" done={done}/>);await action.click(screen.getByRole('button',{name:'Copy code'}));expect(screen.getByText('Select and copy the code manually.')).toBeInTheDocument();expect(screen.getByRole('button',{name:'Done'})).toBeDisabled();await action.click(screen.getByRole('checkbox'));await action.click(screen.getByRole('button',{name:'Done'}));expect(done).toHaveBeenCalledOnce();
});

it.each(['member','moderator','admin'] as Role[])('renders the %s dashboard and role-specific links',async role=>{
  app('/dashboard',()=>undefined,role);
  await screen.findByRole('heading',{name:'Welcome, Alice.'});
  expect(screen.getByText(`${role==='member'?'MEMBER':role==='moderator'?'MODERATOR':'ADMIN'} DASHBOARD`)).toBeInTheDocument();
  expect(Boolean(screen.queryByRole('link',{name:/^Manage members/}))).toBe(role==='admin');
  expect(Boolean(screen.queryByRole('link',{name:/^Review reports/}))).toBe(role!=='member');
});
it.each(['/admin/users','/admin/tags','/moderation','/activity'])('blocks member access to %s before a privileged API request',async path=>{
 const {fetcher}=app(path);
 expect(await screen.findByText('This page is not available for your role.')).toBeInTheDocument();
 expect(fetcher.mock.calls.some(([url])=>url.startsWith('/api/admin/')||url.includes('/moderation/'))).toBe(false);
});
it('publishes a thread with normalized unique tags',async()=>{
 const action=userEvent.setup();let payload:unknown;
 app('/discussions/new',(path,options)=>{if(path==='/api/forum/threads'&&options?.method==='POST'){payload=body(options);return json({...thread,title:'New idea'},201);}return undefined;});
 await screen.findByLabelText('Title');await action.type(screen.getByLabelText('Title'),'New idea');await action.type(screen.getByLabelText('Discussion',{exact:true}),'A useful description');await action.type(screen.getByLabelText('Tags'),'Python, python, JWT');await action.click(screen.getByRole('button',{name:'Publish discussion'}));
 await screen.findByRole('heading',{name:thread.title});expect(payload).toEqual({title:'New idea',description:'A useful description',tags:['python','jwt']});
});
it('rejects more than five tags without submitting',async()=>{
 const action=userEvent.setup();const {fetcher}=app('/discussions/new');await screen.findByLabelText('Title');await action.type(screen.getByLabelText('Title'),'New idea');await action.type(screen.getByLabelText('Discussion',{exact:true}),'Body');await action.type(screen.getByLabelText('Tags'),'one,two,three,four,five,six');await action.click(screen.getByRole('button',{name:'Publish discussion'}));expect(await screen.findByRole('alert')).toHaveTextContent('up to five tags');expect(fetcher.mock.calls.some(([,options])=>options?.method==='POST'&&options.body?.toString().includes('New idea'))).toBe(false);
});
it('allows owner editing and requires explicit deletion confirmation',async()=>{
 const action=userEvent.setup();let value={...thread};let deleted=false;let edit:unknown;
 const {fetcher}=app('/discussions/thread-1',(path,options)=>{if(path==='/api/forum/threads/thread-1'){if(options?.method==='PATCH'){edit=body(options);value={...value,...edit as object};return json(value);}if(options?.method==='DELETE'){deleted=true;return json({deleted:true});}return deleted?json({},404):json(value);}if(path==='/api/forum/threads')return json({items:deleted?[]:[value],next_cursor:null});return undefined;});
 await screen.findByRole('heading',{name:thread.title});await action.click(screen.getByRole('button',{name:'Edit discussion'}));await action.clear(screen.getByLabelText('Title'));await action.type(screen.getByLabelText('Title'),'Edited title');await action.click(screen.getByRole('button',{name:'Save changes'}));await screen.findByRole('heading',{name:'Edited title'});expect(edit).toMatchObject({title:'Edited title'});
 await action.click(screen.getByRole('button',{name:'Delete discussion'}));expect(deleted).toBe(false);await action.click(screen.getByRole('button',{name:'Confirm delete discussion'}));await screen.findByText('A fresh space for good questions.');expect(fetcher.mock.calls.some(([,options])=>options?.method==='DELETE')).toBe(true);
});
it('hides edit/delete controls for content owned by another member',async()=>{
 app('/discussions/thread-1',(path)=>path==='/api/forum/threads/thread-1'?json({...thread,author:{...thread.author,id:'other'}}):undefined);
 await screen.findByRole('heading',{name:thread.title});expect(screen.queryByRole('button',{name:'Edit discussion'})).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'Delete discussion'})).not.toBeInTheDocument();
});
it('posts comments and replies with the correct parent ID',async()=>{
 const action=userEvent.setup();const payloads:unknown[]=[];app('/discussions/thread-1',(path,options)=>{if(path==='/api/forum/threads/thread-1/comments'&&options?.method==='POST'){payloads.push(body(options));return json({id:'new-comment'},201);}return undefined;});
 await screen.findByLabelText('Add to the conversation');await action.type(screen.getByLabelText('Add to the conversation'),'My answer');await action.click(screen.getByRole('button',{name:'Post comment'}));await screen.findByText('An existing answer');await action.click(screen.getByRole('button',{name:'Reply'}));await action.type(screen.getByLabelText('Your reply'),'My reply');await action.click(screen.getByRole('button',{name:'Post reply'}));await vi.waitFor(()=>expect(payloads).toHaveLength(2));expect(payloads).toEqual([{body:'My answer',parent_id:null},{body:'My reply',parent_id:'comment-1'}]);
});
it('edits and deletes an owned comment',async()=>{
 const action=userEvent.setup();let item={...comment};let removed=false;
 app('/discussions/thread-1',(path,options)=>{if(path==='/api/forum/threads/thread-1/comments')return json({items:removed?[]:[item],next_cursor:null});if(path==='/api/forum/comments/comment-1'&&options?.method==='PATCH'){item={...item,...body(options)};return json(item);}if(path==='/api/forum/comments/comment-1'&&options?.method==='DELETE'){removed=true;return json({deleted:true});}return undefined;});
 await screen.findByText('An existing answer');await action.click(screen.getByRole('button',{name:'Edit comment'}));await action.clear(screen.getByLabelText('Edit comment'));await action.type(screen.getByLabelText('Edit comment'),'Edited answer');await action.click(screen.getByRole('button',{name:'Save comment'}));await screen.findByText('Edited answer');await action.click(screen.getByRole('button',{name:'Delete comment'}));expect(removed).toBe(false);await action.click(screen.getByRole('button',{name:'Confirm delete comment'}));await vi.waitFor(()=>expect(screen.queryByText('Edited answer')).not.toBeInTheDocument());
});
it('toggles thread likes using PUT then DELETE',async()=>{
 const action=userEvent.setup();let liked=false;const methods:string[]=[];
 app('/discussions/thread-1',(path,options)=>{if(path.endsWith('/thread-1/like')){methods.push(options?.method!);liked=options?.method==='PUT';return json({liked,like_count:liked?1:0});}if(path==='/api/forum/threads/thread-1')return json({...thread,liked_by_me:liked,like_count:liked?1:0});return undefined;});
 await screen.findByRole('button',{name:'Like thread'});await action.click(screen.getByRole('button',{name:'Like thread'}));await action.click(await screen.findByRole('button',{name:'Unlike thread'}));await vi.waitFor(()=>expect(methods).toEqual(['PUT','DELETE']));
});
it('submits a report with the defined reason and target',async()=>{
 const action=userEvent.setup();let payload:unknown;app('/discussions/thread-1',(path,options)=>{if(path==='/api/forum/reports'){payload=body(options);return json({status:'open'},201);}return undefined;});
 await screen.findByRole('button',{name:'Report thread'});await action.click(screen.getByRole('button',{name:'Report thread'}));await action.selectOptions(screen.getByLabelText('Reason'),'harassment');await action.type(screen.getByLabelText('Additional context'),'Please review');await action.click(screen.getByRole('button',{name:'Submit report'}));await screen.findByText(/Report submitted/);expect(payload).toEqual({target_type:'thread',target_id:'thread-1',reason:'harassment',note:'Please review'});
});
it('searches with filters and renders snippets as text',async()=>{
 const action=userEvent.setup();const {fetcher}=app('/search',(path)=>path.startsWith('/api/search?')?json({items:[{type:'comment',id:'comment-1',thread_id:'thread-1',title:null,thread_title:'Matching discussion',snippet:'<b data-injection="yes">token</b>',author_username:'bob',created_at:thread.created_at}],next_cursor:null}):undefined);
 await screen.findByLabelText('Search',{exact:true});await action.type(screen.getByLabelText('Search',{exact:true}),' token ');await action.selectOptions(screen.getByLabelText('Content type'),'comment');await action.type(screen.getByLabelText('Tag',{exact:true}),'python');await action.click(screen.getByRole('button',{name:'Search'}));const link=await screen.findByRole('link',{name:'Matching discussion'});expect(link).toHaveAttribute('href','/discussions/thread-1#comment-comment-1');expect(document.querySelector('[data-injection]')).toBeNull();expect(fetcher.mock.calls.some(([url])=>url.includes('q=token&type=comment&tag=python'))).toBe(true);
});
it('marks one notification and all notifications read',async()=>{
 const action=userEvent.setup();let read=false;let all=false;
 app('/notifications',(path,options)=>{if(path==='/api/notifications/unread-count')return json({unread_count:read?0:1});if(path==='/api/notifications/note-1/read'){read=true;return json({});}if(path==='/api/notifications/read-all'){all=true;return json({});}if(path.startsWith('/api/notifications'))return json({items:[{id:'note-1',type:'mention',actor:{id:'other',username:'bob'},thread_id:'thread-1',comment_id:null,read_at:read?thread.created_at:null,created_at:thread.created_at}],next_cursor:null});return undefined;});
 await screen.findByRole('button',{name:'Mark read'});await action.click(screen.getByRole('button',{name:'Mark read'}));await vi.waitFor(()=>expect(screen.queryByRole('button',{name:'Mark read'})).not.toBeInTheDocument());await action.click(screen.getByRole('button',{name:'Mark all read'}));await vi.waitFor(()=>expect(all).toBe(true));
});
it('updates the profile and header from the wrapped response',async()=>{
 const action=userEvent.setup();let payload:unknown;app('/profile',(path,options)=>{if(path==='/api/users/me'&&options?.method==='PATCH'){payload=body(options);return json({user:{...person,display_name:'Updated name'}});}return undefined;});
 await screen.findByLabelText('Display name');await action.clear(screen.getByLabelText('Display name'));await action.type(screen.getByLabelText('Display name'),'Updated name');await action.click(screen.getByRole('button',{name:'Save profile'}));await screen.findByText('Profile updated.');expect(payload).toMatchObject({display_name:'Updated name',bio:'Hello',avatar_url:null});expect(screen.getByText('Updated name')).toBeInTheDocument();
});
it('changes username and refreshes the session',async()=>{
 const action=userEvent.setup();let payload:unknown;const {fetcher}=app('/profile',(path,options)=>{if(path==='/api/users/me/username'){payload=body(options);return json({user:{...person,username:'alice_new'}});}return undefined;});await screen.findByLabelText('New username');await action.clear(screen.getByLabelText('New username'));await action.type(screen.getByLabelText('New username'),'alice_new');await action.click(screen.getByRole('button',{name:'Change username'}));await screen.findByText('Username updated.');expect(payload).toEqual({username:'alice_new'});expect(fetcher.mock.calls.filter(([url])=>url==='/api/auth/refresh').length).toBeGreaterThan(1);
});
it('changes password using existing server field names',async()=>{
 const action=userEvent.setup();let payload:unknown;app('/profile',(path,options)=>{if(path==='/api/users/me/password'){payload=body(options);return json({});}return undefined;});await screen.findByLabelText('Current password');await action.type(screen.getByLabelText('Current password'),'Devpass123!');await action.type(screen.getByLabelText('New password',{exact:true}),'Devpass456!');await action.type(screen.getByLabelText('Confirm new password'),'Devpass456!');await action.click(screen.getByRole('button',{name:'Change password'}));await screen.findByText(/Password changed/);expect(payload).toEqual({current_password:'Devpass123!',new_password:'Devpass456!'});
});
it('regenerates a recovery code only after confirmation and requires saving',async()=>{
 const action=userEvent.setup();let issued=false;app('/profile',(path)=>{if(path==='/api/users/me/recovery-code'){issued=true;return json({recovery_code:'ABCD-EFGH-IJKL-MNOP',recovery_code_notice:'Shown once.'});}return undefined;});await screen.findByRole('button',{name:'Generate new recovery code'});await action.click(screen.getByRole('button',{name:'Generate new recovery code'}));expect(issued).toBe(false);await action.click(screen.getByRole('button',{name:'Confirm new recovery code'}));await screen.findByLabelText('Your recovery code');expect(screen.getByRole('button',{name:'Done'})).toBeDisabled();await action.click(screen.getByRole('checkbox',{name:/saved or securely/}));await action.click(screen.getByRole('button',{name:'Done'}));expect(screen.queryByLabelText('Your recovery code')).not.toBeInTheDocument();
});
it.each(['resolve','dismiss'])('handles moderator report %s with confirmation',async operation=>{
 const action=userEvent.setup();let payload:unknown;let completed=false;
 app('/moderation',(path,options)=>{if(path.includes('/moderation/reports/report-1/')){payload=options.body?body(options):null;completed=true;return json({});}if(path.startsWith('/api/forum/moderation/reports'))return json({items:completed?[]:[{id:'report-1',reporter_id:'other',target_type:'thread',target_id:'thread-1',reason:'spam',note:'Review this',status:'open',created_at:thread.created_at}],next_cursor:null});return undefined;},'moderator');
 await screen.findByText('Review this');if(operation==='resolve')await action.click(screen.getByRole('checkbox',{name:/Delete the reported content/}));await action.click(screen.getByRole('button',{name:operation==='resolve'?'Resolve report':'Dismiss report'}));expect(completed).toBe(false);await action.click(screen.getByRole('button',{name:operation==='resolve'?'Confirm resolve':'Confirm dismiss'}));await screen.findByText('No open reports.');if(operation==='resolve')expect(payload).toEqual({action:'delete_content',note:null});else expect(payload).toBeNull();
});
const member={...person,id:'other',username:'bob',role:'member',created_at:thread.created_at,updated_at:thread.created_at};
it('reads the admin users envelope and changes a role',async()=>{
 const action=userEvent.setup();let changed:unknown;app('/admin/users',(path,options)=>{if(path==='/api/admin/users/other/role'){changed=body(options);return json(member);}if(path.startsWith('/api/admin/users'))return json({users:[member],next_cursor:null});return undefined;},'admin');await screen.findByRole('button',{name:'Manage'});await action.click(screen.getByRole('button',{name:'Manage'}));await action.selectOptions(screen.getByLabelText('Role',{exact:true}),'moderator');await action.click(screen.getByRole('button',{name:'Save role'}));await action.click(screen.getByRole('button',{name:'Confirm account action'}));await vi.waitFor(()=>expect(changed).toEqual({role:'moderator'}));
});
it.each(['active','disabled'])('handles member status %s safely',async status=>{
 const action=userEvent.setup();let changed=false;app('/admin/users',(path)=>{if(path===`/api/admin/users/other/${status==='active'?'disable':'enable'}`){changed=true;return json({});}if(path.startsWith('/api/admin/users'))return json({users:[{...member,status}],next_cursor:null});return undefined;},'admin');await screen.findByRole('button',{name:'Manage'});await action.click(screen.getByRole('button',{name:'Manage'}));if(status==='active')await action.type(screen.getByLabelText('Reason for disabling'),'Repeated spam');await action.click(screen.getByRole('button',{name:status==='active'?'Disable account':'Enable account'}));expect(changed).toBe(false);await action.click(screen.getByRole('button',{name:'Confirm account action'}));await vi.waitFor(()=>expect(changed).toBe(true));
});
it('prevents an administrator changing their own role',async()=>{
 const action=userEvent.setup();app('/admin/users',path=>path.startsWith('/api/admin/users')?json({users:[{...member,id:'user-1',role:'admin'}],next_cursor:null}):undefined,'admin');await screen.findByRole('button',{name:'Manage'});await action.click(screen.getByRole('button',{name:'Manage'}));expect(screen.getByRole('button',{name:'Save role'})).toBeDisabled();
});
it('issues an admin recovery code in a non-cached receipt',async()=>{
 const action=userEvent.setup();const {cache}=app('/admin/users',path=>path==='/api/admin/users/other/recovery-code'?json({recovery_code:'ABCD-EFGH-IJKL-MNOP',recovery_code_notice:'Valid for 24 hours.'}):path.startsWith('/api/admin/users')?json({users:[member],next_cursor:null}):undefined,'admin');await screen.findByRole('button',{name:'Manage'});await action.click(screen.getByRole('button',{name:'Manage'}));await action.click(screen.getByRole('button',{name:'Issue 24-hour recovery code'}));await action.click(screen.getByRole('button',{name:'Confirm account action'}));await screen.findByLabelText('Your recovery code');expect(cache.getMutationCache().getAll()).toHaveLength(0);
});
it('removes a tag through the defined UUID endpoint',async()=>{
 const action=userEvent.setup();const tag='11111111-1111-4111-8111-111111111111';let deleted=false;app('/admin/tags',(path,options)=>{if(path===`/api/forum/admin/tags/${tag}`&&options?.method==='DELETE'){deleted=true;return json(null,204);}return undefined;},'admin');await screen.findByLabelText('Tag ID');await action.type(screen.getByLabelText('Tag ID'),tag);await action.click(screen.getByRole('button',{name:'Remove tag'}));expect(deleted).toBe(false);await action.click(screen.getByRole('button',{name:'Confirm remove tag'}));expect(await screen.findByText('Tag removed.')).toBeInTheDocument();
});
it('renders role-filtered activity data and supports filters',async()=>{
 const action=userEvent.setup();const {fetcher}=app('/activity',path=>path.startsWith('/api/admin/activity-log')?json({items:[{id:'log-1',actor_id:'other',action:'thread_deleted_by_moderator',target_type:'thread',target_id:'thread-1',metadata:{note:'reviewed'},created_at:thread.created_at}],next_cursor:null}):undefined,'moderator');await screen.findByText('thread deleted by moderator');await action.type(screen.getByLabelText('Action',{exact:true}),'thread_deleted');await action.click(screen.getByRole('button',{name:'Filter activity'}));await vi.waitFor(()=>expect(fetcher.mock.calls.some(([path])=>path.includes('action=thread_deleted'))).toBe(true));
});
it('loads public profiles using the user wrapper',async()=>{
 app('/members/bob',path=>path==='/api/users/bob'?json({user:{...person,username:'bob',display_name:'Bob',bio:'A public bio'}}):undefined);await screen.findByText('A public bio');expect(screen.getByRole('heading',{name:'Bob'})).toBeInTheDocument();
});
