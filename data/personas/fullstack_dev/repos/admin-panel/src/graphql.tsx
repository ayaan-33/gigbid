import { ApolloServer } from "@apollo/server";
import DataLoader from "dataloader";

const typeDefs = `#graphql
  type Order { id: ID!, total: Float!, customer: Customer! }
  type Customer { id: ID!, name: String! }
  type Query { orders(limit: Int = 20): [Order!]! }
`;

export const customerLoader = new DataLoader(async (ids: readonly string[]) => fetchCustomers(ids));
declare function fetchCustomers(ids: readonly string[]): Promise<{ id: string; name: string }[]>;
export const server = new ApolloServer({ typeDefs, resolvers: {} });
