/**
 * Stripe webhook handler — updates subscriptions table on checkout.session.completed.
 * Called server-to-server by Stripe. Deploy with --no-verify-jwt.
 */
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import Stripe from "https://esm.sh/stripe@14?target=deno";

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY")!, {
  apiVersion: "2023-10-16",
});
const endpointSecret = Deno.env.get("STRIPE_WEBHOOK_SECRET")!;

Deno.serve(async (req) => {
  const signature = req.headers.get("stripe-signature")!;
  const body = await req.text();

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(body, signature, endpointSecret);
  } catch (err) {
    return new Response(`Webhook Error: ${err.message}`, { status: 400 });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );

  switch (event.type) {
    case "checkout.session.completed": {
      const session = event.data.object as Stripe.Checkout.Session;
      const email =
        session.customer_email || session.customer_details?.email;

      if (!email) break;

      const { data: profile } = await supabase
        .from("profiles")
        .select("id")
        .eq("email", email)
        .single();

      if (!profile) break;

      const { data: tier } = await supabase
        .from("subscription_tiers")
        .select("id")
        .eq("name", "starter")
        .single();

      await supabase.from("subscriptions").upsert(
        {
          user_id: profile.id,
          tier_id: tier?.id,
          stripe_customer_id: session.customer as string,
          stripe_session_id: session.id,
          stripe_payment_intent: session.payment_intent as string,
          status: "active",
        },
        { onConflict: "user_id" }
      );

      break;
    }

    // Future: customer.subscription.updated, customer.subscription.deleted, invoice.payment_failed
  }

  return new Response(JSON.stringify({ received: true }), { status: 200 });
});
