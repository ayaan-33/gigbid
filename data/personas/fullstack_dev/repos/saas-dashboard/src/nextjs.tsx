import { notFound } from "next/navigation";

export const revalidate = 300;

export default async function Page({ params }: { params: { slug: string } }) {
  const res = await fetch(`${process.env.API_URL}/items/${params.slug}`, { next: { revalidate } });
  if (!res.ok) notFound();
  const item = await res.json();
  return <main><h1>{item.title}</h1></main>;
}
