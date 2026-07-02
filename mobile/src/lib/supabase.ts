import 'react-native-url-polyfill/auto';
import { createClient } from '@supabase/supabase-js';

// The PUBLISHABLE key is safe to ship in the app — it is read-only by design
// (Row Level Security on the database only allows public SELECT). All writes
// happen server-side in the Python pipeline using the secret key.
const SUPABASE_URL = 'https://gutsqtshsjjkbydjuojk.supabase.co';
const SUPABASE_PUBLISHABLE_KEY = 'sb_publishable_SjbNv-ARZoSPsd70I0G5Tw_XnzS5lOi';

export const supabase = createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
  auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
});
