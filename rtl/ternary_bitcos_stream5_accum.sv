// Five-position/cycle BITCOS streaming row accumulator.
//
// This is throughput-matched to the T-ACE five-trit streaming baseline while
// retaining the lossless natural-sparsity representation.
module ternary_bitcos_stream5_accum #(
    parameter int ACT_W = 8,
    parameter int ACC_W = 24
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    start,
    input  logic [2:0]              initial_sign_offset,
    input  logic                    valid,
    input  logic                    last,
    input  logic [5*ACT_W-1:0]      activations,
    input  logic [4:0]              presence,
    input  logic [7:0]              current_sign_byte,
    input  logic [7:0]              next_sign_byte,
    output logic                    advance_sign_byte,
    output logic [2:0]              sign_offset,
    output logic signed [ACC_W-1:0] dot,
    output logic                    done
);
    logic [9:0] weights_2b;
    logic [2:0] consumed_signs;
    logic signed [ACC_W-1:0] partial;
    logic signed [ACC_W-1:0] acc;

    bitcos_stream5_bytecursor_decoder decode (
        .clk(clk),
        .rst_n(rst_n),
        .start_block(start),
        .initial_offset(initial_sign_offset),
        .advance(valid),
        .current_sign_byte(current_sign_byte),
        .next_sign_byte(next_sign_byte),
        .presence(presence),
        .weights_2b(weights_2b),
        .consumed_signs(consumed_signs),
        .offset_state(sign_offset),
        .advance_sign_byte(advance_sign_byte)
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
