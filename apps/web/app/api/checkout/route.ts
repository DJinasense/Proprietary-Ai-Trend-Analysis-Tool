import { NextResponse } from "next/server";
import Stripe from "stripe";

const stripeSecret = process.env.STRIPE_SECRET_KEY || "";
const stripe = stripeSecret ? new Stripe(stripeSecret) : null;

export async function POST(req: Request) {
  try {
    const body = await req.json().catch(() => ({}));
    const productId = body.productId || "prod_VKJhWwKnR7dstx";
    const paymentLink = process.env.NEXT_PUBLIC_STRIPE_PAYMENT_LINK || "";
    const origin = req.headers.get("origin") || "https://muse.dgrvip.net";

    if (!stripe) {
      if (paymentLink) {
        return NextResponse.json({ url: paymentLink });
      }
      return NextResponse.json(
        {
          error:
            "Stripe Secret Key (STRIPE_SECRET_KEY) is not configured in environment settings.",
        },
        { status: 400 }
      );
    }

    // When product ID is specified, pass product ID in price_data
    const lineItem: Stripe.Checkout.SessionCreateParams.LineItem = productId
      ? {
          price_data: {
            currency: "usd",
            product: productId,
            unit_amount: 1399,
            recurring: { interval: "month" },
          },
          quantity: 1,
        }
      : {
          price_data: {
            currency: "usd",
            unit_amount: 1399,
            recurring: { interval: "month" },
            product_data: {
              name: "MUSE Pro Membership",
              description: "Unlimited full-track audio analysis & narrative synthesis",
            },
          },
          quantity: 1,
        };

    const session = await stripe.checkout.sessions.create({
      payment_method_types: ["card"],
      line_items: [lineItem],
      mode: "subscription",
      success_url: `${origin}/?checkout=success`,
      cancel_url: `${origin}/?checkout=cancel`,
    });

    return NextResponse.json({ url: session.url });
  } catch (err: any) {
    console.error("Stripe Checkout Error:", err);
    return NextResponse.json(
      { error: err.message || "Stripe checkout session failed" },
      { status: 500 }
    );
  }
}
