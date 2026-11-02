import { notFound } from "next/navigation";
import ReviewHome from "./ReviewHome";

export const dynamic = "force-dynamic";
export default function ReviewPage() {
  if(process.env.REVIEW_MODE!=="true") notFound();
  return <ReviewHome />;
}
