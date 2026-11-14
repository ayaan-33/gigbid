import Stripe from "stripe";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

export async function handleWebhook(rawBody: Buffer, signature: string) {
  const event = stripe.webhooks.constructEvent(rawBody, signature, process.env.STRIPE_WEBHOOK_SECRET!);
  switch (event.type) {
    case "invoice.payment_failed":
      return markPastDue(event.data.object.customer as string);
    case "customer.subscription.updated":
      return syncSubscription(event.data.object);
  }
}
declare function markPastDue(id: string): Promise<void>;
declare function syncSubscription(s: unknown): Promise<void>;
