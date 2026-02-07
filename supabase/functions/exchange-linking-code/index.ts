/**
 * Exchange a linking code for Supabase session tokens (desktop app).
 * Caller has no token yet. Deploy with --no-verify-jwt.
 */
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  const { code } = await req.json();

  const adminClient = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );

  const { data, error } = await adminClient
    .from("linking_codes")
    .select("access_token, refresh_token, user_id")
    .eq("code", code.toUpperCase().trim())
    .eq("used", false)
    .gt("expires_at", new Date().toISOString())
    .single();

  if (error || !data) {
    return new Response(
      JSON.stringify({ error: "Invalid or expired code" }),
      {
        status: 400,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      }
    );
  }

  await adminClient
    .from("linking_codes")
    .update({ used: true })
    .eq("code", code.toUpperCase().trim());

  return new Response(
    JSON.stringify({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
    }),
    {
      status: 200,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    }
  );
});
