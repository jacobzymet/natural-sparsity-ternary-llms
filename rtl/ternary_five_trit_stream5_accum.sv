// Streaming five-trit row accumulator.
//
// One packed byte represents five ternary weights. Each accepted cycle
// decodes five weights, computes a five-activation partial dot product, and
// accumulates it into the current output row.
//
// Protocol:
// - pulse start on a cycle before the first valid data cycle
// - valid accepts one 5-weight / 5-activation group
// - assert last with the final valid group
// - done pulses with dot containing the completed row result
module ternary_five_trit_stream5_accum #(
    parameter int ACT_W = 8,
    parameter int ACC_W = 24
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    start,
    input  logic                    valid,
    input  logic                    last,
    input  logic [5*ACT_W-1:0]      activations,
    input  logic [7:0]              packed_weights,
    output logic signed [ACC_W-1:0] dot,
    output logic                    done
);
    logic [9:0] weights_2b;
    logic signed [ACC_W-1:0] partial;
    logic signed [ACC_W-1:0] acc;

    five_trit_tace_byte_decoder decode (
        .packed_byte(packed_weights),
        .weights_2b(weights_2b)
    );

    ternary_dense2_parallel_gemv #(
        .LANES(5),
        .ACT_W(ACT_W),
        .ACC_W(ACC_W)
    ) partial_dot (
        .activations(activations),
        .weights_2b(weights_2b),
        .dot(partial)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc <= '0;
            dot <= '0;
            done <= 1'b0;
        end else begin
            done <= 1'b0;
            if (start) begin
                acc <= '0;
            end else if (valid) begin
                if (last) begin
                    dot <= acc + partial;
                    acc <= '0;
                    done <= 1'b1;
                end else begin
                    acc <= acc + partial;
                end
            end
        end
    end
endmodule
