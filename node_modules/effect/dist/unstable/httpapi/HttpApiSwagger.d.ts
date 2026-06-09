import type * as Layer from "../../Layer.ts";
import * as HttpRouter from "../http/HttpRouter.ts";
import type * as HttpApi from "./HttpApi.ts";
import type * as HttpApiGroup from "./HttpApiGroup.ts";
/**
 * Mounts Swagger UI for an `HttpApi` at the configured path, defaulting to
 * `/docs`, using the OpenAPI specification generated from the API.
 *
 * @category layers
 * @since 4.0.0
 */
export declare const layer: <Id extends string, Groups extends HttpApiGroup.Any>(api: HttpApi.HttpApi<Id, Groups>, options?: {
    readonly path?: `/${string}` | undefined;
}) => Layer.Layer<never, never, HttpRouter.HttpRouter>;
//# sourceMappingURL=HttpApiSwagger.d.ts.map