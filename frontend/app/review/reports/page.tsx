import { notFound } from "next/navigation";
import ReviewReports from "./ReviewReports";
export const dynamic="force-dynamic";
export default function Page(){if(process.env.REVIEW_MODE!=="true")notFound();return <ReviewReports/>;}
